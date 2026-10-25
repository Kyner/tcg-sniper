// Gestão: Atividade, a lista única do que os serviços fizeram (coletas, buscas, leituras, checkouts, IA, mensagens,
// backups, avisos e ações da gestão). Filtros na URL; "Carregar mais" acrescenta a próxima página pelo cursor.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { chamarApi } from "../../api";
import { Carregando } from "../../componentes/Carregando";
import { TextoWhatsApp } from "../../componentes/TextoWhatsApp";
import { enderecoAmazon } from "../../enderecos";
import { useFiltrosUrl } from "../../filtrosUrl";
import { dataHora } from "../../formato";
import { useSessao } from "../../sessao";
import type { LinhaAtividade, PaginaAtividade, SituacaoAtividade } from "../../tipos";

export const PADROES = { servico: "", o_que: "", situacao: "", de: "", ate: "", busca: "", reinicios: "" };
const ESPERA_BUSCA_MS = 350;

const SERVICOS: Record<string, string> = {
  liga: "LigaMagic", amazon_busca: "Amazon · busca", amazon_monitor: "Amazon · monitor", casador: "Casador",
  whatsapp: "WhatsApp", backup: "Backup",
};
const O_QUE: Record<string, string> = {
  coleta_liga: "coleta da Liga", busca: "busca", leitura_monitor: "leitura do monitor", checkout: "checkout", ia: "IA",
  mensagem: "mensagem", backup: "backup", aviso: "aviso", acao_gestao: "ação da gestão",
};
const SITUACOES: Record<string, string> = { ok: "ok", parcial: "parcial", falha: "falha", problemas: "problemas (parcial e falha)" };
const SELO: Record<SituacaoAtividade, string> = { ok: "badge badge-success", parcial: "badge badge-warning", falha: "badge badge-error" };

const ROTULO_MENSAGEM: Record<string, string> = {
  enviada: "enviada", descartada: "descartada", pendente: "na fila", expirada: "expirou sem sair", falha: "falha",
};
const SITUACAO_MENSAGEM: Record<string, SituacaoAtividade> = {
  enviada: "ok", descartada: "ok", pendente: "parcial", expirada: "parcial", falha: "falha",
};

const doisDigitos = (n: number) => String(n).padStart(2, "0");

/** "2026-10-20" + hora local do navegador -> ISO com o deslocamento do fuso (a API recusa data sem fuso). */
function comFuso(dia: string, h: number, m: number, s: number): string {
  const [ano, mes, d] = dia.split("-").map(Number);
  const data = new Date(ano, mes - 1, d, h, m, s);
  const deslocamento = -data.getTimezoneOffset();
  const sinal = deslocamento >= 0 ? "+" : "-";
  const abs = Math.abs(deslocamento);
  return `${dia}T${doisDigitos(h)}:${doisDigitos(m)}:${doisDigitos(s)}${sinal}${doisDigitos(Math.floor(abs / 60))}:${doisDigitos(abs % 60)}`;
}
export const inicioDoDia = (dia: string) => comFuso(dia, 0, 0, 0);
export const fimDoDia = (dia: string) => comFuso(dia, 23, 59, 59);

function montarQuery(f: Record<string, string>, cursor: string | null): string {
  const partes: string[] = [];
  const mais = (k: string, v: string) => partes.push(`${k}=${encodeURIComponent(v)}`);
  if (f.servico) mais("servico", f.servico);
  if (f.o_que) mais("o_que", f.o_que);
  if (f.situacao) mais("situacao", f.situacao);
  if (f.de) mais("de", inicioDoDia(f.de));
  if (f.ate) mais("ate", fimDoDia(f.ate));
  if (f.busca) mais("busca", f.busca);
  if (f.reinicios === "true") mais("reinicios", "true");
  if (cursor) mais("cursor", cursor);
  return partes.join("&");
}

function rotuloChave(chave: string): string {
  return chave.replace(/_/g, " ");
}

function Detalhe({ linha }: { linha: LinhaAtividade }) {
  const { texto, ...resto } = linha.detalhe as Record<string, string | number | null>;
  const ehMensagem = linha.o_que === "mensagem";
  const campos = Object.entries(resto).filter(([, v]) => v !== null && v !== "");
  return (
    <div className="space-y-2 rounded-box bg-base-200 p-3 text-sm">
      {campos.length > 0 && (
        <dl className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2">
          {campos.map(([k, v]) => (
            <div key={k} className="flex min-w-0 flex-col">
              <dt className="text-xs opacity-60">{rotuloChave(k)}</dt>
              <dd className="break-words">{String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {ehMensagem && (
        <div>
          <div className="text-xs opacity-60">texto</div>
          {typeof texto === "string" ? <TextoWhatsApp texto={texto} /> : <p className="italic opacity-70">texto oculto</p>}
        </div>
      )}
      <p className="break-words">{linha.resultado}</p>
    </div>
  );
}

function Acoes({ linha, aoAgir }: { linha: LinhaAtividade; aoAgir: (l: LinhaAtividade, acao: "reenviar" | "descartar") => Promise<string | null> }) {
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const status = String(linha.detalhe.status ?? "");
  const reenviavel = (status === "falha" || status === "expirada") && linha.detalhe.destino !== "individual";
  const descartavel = status === "pendente" || status === "falha" || status === "expirada";
  if (!reenviavel && !descartavel) return null;
  const agir = async (acao: "reenviar" | "descartar") => {
    setOcupado(true);
    setErro(null);
    const msg = await aoAgir(linha, acao);
    setErro(msg);
    setOcupado(false);
  };
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {reenviavel && (
          <button type="button" className="btn btn-sm btn-primary" disabled={ocupado} onClick={() => void agir("reenviar")}>Reenviar</button>
        )}
        {descartavel && (
          <button type="button" className="btn btn-sm btn-outline" disabled={ocupado} onClick={() => void agir("descartar")}>Descartar</button>
        )}
      </div>
      {erro && <div role="alert" className="alert alert-error alert-soft py-2 text-sm"><span>{erro}</span></div>}
    </div>
  );
}

export function Atividade() {
  const { tratarErro, pode } = useSessao();
  const [filtros, mudar] = useFiltrosUrl(PADROES);
  const [texto, setTexto] = useState(filtros.busca);
  const [itens, setItens] = useState<LinhaAtividade[] | null>(null);
  const [proximo, setProximo] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [maisCarregando, setMaisCarregando] = useState(false);
  const [abertas, setAbertas] = useState<Set<string>>(new Set());
  const ultimoCursor = useRef<string | null>(null);
  const query = montarQuery(filtros, null);
  const podeAgir = pode("reenviar_mensagens");

  useEffect(() => { setTexto(filtros.busca); }, [filtros.busca]);
  useEffect(() => {
    if (texto === filtros.busca) return;
    const id = window.setTimeout(() => mudar({ busca: texto.trim() }), ESPERA_BUSCA_MS);
    return () => window.clearTimeout(id);
  }, [texto, filtros.busca, mudar]);

  const carregar = useCallback(async (cursor: string | null, sinal?: { cancelado: boolean }) => {
    setErro(null);
    ultimoCursor.current = cursor;
    if (cursor) setMaisCarregando(true);
    try {
      const q = cursor ? `${query}${query ? "&" : ""}cursor=${encodeURIComponent(cursor)}` : query;
      const r = await chamarApi<PaginaAtividade>(`/api/gestao/atividade${q ? `?${q}` : ""}`);
      if (sinal?.cancelado) return;
      setItens((antes) => (cursor && antes ? [...antes, ...r.itens] : r.itens));
      setProximo(r.proximo);
    } catch (e) {
      if (sinal?.cancelado) return;
      setErro(tratarErro(e));
    } finally {
      if (!sinal?.cancelado) setMaisCarregando(false);
    }
  }, [query, tratarErro]);

  useEffect(() => {
    const sinal = { cancelado: false };
    void carregar(null, sinal);
    return () => { sinal.cancelado = true; };
  }, [carregar]);

  const agir = useCallback(async (linha: LinhaAtividade, acao: "reenviar" | "descartar"): Promise<string | null> => {
    const id = linha.detalhe.mensagem_id;
    try {
      const r = await chamarApi<{ status: string }>(`/api/gestao/mensagens/${id}/${acao}`, { metodo: "POST" });
      setItens((antes) => (antes ?? []).map((l) => {
        if (l.chave !== linha.chave) return l;
        const rotulo = ROTULO_MENSAGEM[r.status] ?? r.status;
        const corte = l.resultado.indexOf(" · ");
        return {
          ...l, situacao: SITUACAO_MENSAGEM[r.status] ?? l.situacao, detalhe: { ...l.detalhe, status: r.status },
          resultado: corte >= 0 ? `${rotulo}${l.resultado.slice(corte)}` : rotulo,
        };
      }));
      return null;
    } catch (e) {
      return tratarErro(e) ?? "Não deu para concluir.";
    }
  }, [tratarErro]);

  const alternar = (chave: string) => setAbertas((a) => {
    const novo = new Set(a);
    if (!novo.delete(chave)) novo.add(chave);
    return novo;
  });

  const filtrado = Object.keys(PADROES).some((k) => filtros[k as keyof typeof PADROES] !== "");
  const limpar = () => { setTexto(""); mudar({ ...PADROES }); };

  if (itens === null && !erro) return <Carregando />;

  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold">Atividade</h1>

      <fieldset className="fieldset grid grid-cols-1 gap-3 rounded-box bg-base-100 p-3 shadow-sm sm:grid-cols-2 lg:grid-cols-4">
        <legend className="fieldset-legend">Filtros</legend>
        <input type="search" className="input w-full" aria-label="Buscar" placeholder="Buscar produto, ASIN ou texto"
          maxLength={100} value={texto} onChange={(ev) => setTexto(ev.target.value)} />
        <select className="select w-full" aria-label="Serviço" value={filtros.servico}
          onChange={(ev) => mudar({ servico: ev.target.value })}>
          <option value="">Todos os serviços</option>
          {Object.entries(SERVICOS).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
        </select>
        <select className="select w-full" aria-label="O quê" value={filtros.o_que}
          onChange={(ev) => mudar({ o_que: ev.target.value })}>
          <option value="">Tudo</option>
          {Object.entries(O_QUE).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
        </select>
        <select className="select w-full" aria-label="Situação" value={filtros.situacao}
          onChange={(ev) => mudar({ situacao: ev.target.value })}>
          <option value="">Todas as situações</option>
          {Object.entries(SITUACOES).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
        </select>
        <label className="floating-label">
          <span>De</span>
          <input type="date" className="input w-full" aria-label="De" value={filtros.de}
            onChange={(ev) => mudar({ de: ev.target.value })} />
        </label>
        <label className="floating-label">
          <span>Até</span>
          <input type="date" className="input w-full" aria-label="Até" value={filtros.ate}
            onChange={(ev) => mudar({ ate: ev.target.value })} />
        </label>
        <label className="label cursor-pointer justify-start gap-2">
          <input type="checkbox" className="toggle toggle-sm" checked={filtros.reinicios === "true"}
            onChange={(ev) => mudar({ reinicios: ev.target.checked ? "true" : "" })} />
          <span>Mostrar reinícios</span>
        </label>
        <p className="text-xs opacity-70 sm:col-span-2 lg:col-span-4">
          As leituras do monitor só aparecem com o filtro “leitura do monitor” ou com uma busca por produto ou ASIN
          (são centenas por hora).
        </p>
      </fieldset>

      {erro && (
        <div role="alert" className="alert alert-error">
          <span>{erro}</span>
          <button type="button" className="btn btn-sm" onClick={() => void carregar(ultimoCursor.current)}>Tentar de novo</button>
        </div>
      )}

      {itens && itens.length === 0 && !erro && (
        <div className="space-y-3 py-6 text-center">
          <p className="opacity-70">{filtrado ? "Nenhuma atividade com esses filtros" : "Nenhuma atividade registrada"}</p>
          {filtrado && <button type="button" className="btn btn-sm" onClick={limpar}>Limpar filtros</button>}
        </div>
      )}

      {itens && itens.length > 0 && (
        <ul className="list rounded-box bg-base-100 shadow-sm" aria-label="Atividade">
          {itens.map((l) => {
            const aberta = abertas.has(l.chave);
            const ehMensagem = l.o_que === "mensagem" && l.detalhe.mensagem_id != null;
            return (
              <li key={l.chave} className="list-row">
                <div className="list-col-grow min-w-0 space-y-1">
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="opacity-70">{dataHora(l.em)}</span>
                    {l.servico && <span className="badge badge-ghost badge-sm">{SERVICOS[l.servico] ?? l.servico}</span>}
                    <span className="badge badge-outline badge-sm">{O_QUE[l.o_que] ?? l.o_que}</span>
                    <span className={SELO[l.situacao]}>{l.situacao}</span>
                  </div>
                  <div className="tooltip max-w-full" data-tip={l.resultado}>
                    <span className="block max-w-full truncate text-left text-sm">{l.resultado}</span>
                  </div>
                  {(l.produto || l.asin || l.custo_usd) && (
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                      {l.produto && l.produto_id != null && (
                        <Link className="link max-w-full truncate" to={`/gestao/produtos/${l.produto_id}`}>{l.produto}</Link>
                      )}
                      {l.asin && (
                        <a className="link" href={enderecoAmazon(l.asin)} target="_blank" rel="noopener noreferrer">{l.asin}</a>
                      )}
                      {l.custo_usd && <span className="opacity-70">US$ {l.custo_usd}</span>}
                    </div>
                  )}
                  <button type="button" className="btn btn-xs btn-ghost" aria-expanded={aberta} onClick={() => alternar(l.chave)}>
                    Detalhes
                  </button>
                  {aberta && (
                    <div className="space-y-2">
                      <Detalhe linha={l} />
                      {ehMensagem && podeAgir && <Acoes linha={l} aoAgir={agir} />}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {proximo && (
        <div className="text-center">
          <button type="button" className="btn btn-sm" disabled={maisCarregando} onClick={() => void carregar(proximo)}>
            Carregar mais
          </button>
        </div>
      )}
    </section>
  );
}
