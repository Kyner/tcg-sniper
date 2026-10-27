// Gestão: revisão dos anúncios da Amazon de um produto da Liga. A query da lista (filtros, ordem e página) vem
// na URL e segue igual para a API, para "Voltar à lista" e para Anterior/Pular/Próximo.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { chamarApi, ErroApi } from "../../api";
import { CartaoAnuncio } from "../../componentes/CartaoAnuncio";
import { Carregando } from "../../componentes/Carregando";
import { Foto } from "../../componentes/Foto";
import { ModalOutroProduto } from "../../componentes/ModalOutroProduto";
import { useFiltrosUrl } from "../../filtrosUrl";
import { reais } from "../../formato";
import { useSessao } from "../../sessao";
import type {
  AcaoCasamento, AnuncioRevisao, DecisaoCasamento, GrupoRevisao, ListaCasamentos, MensagemAcao, ProdutoParecido,
  RevisaoCasamento as Revisao,
} from "../../tipos";
import { montarQuery, PADROES } from "./Casamentos";

type Grupos = Record<GrupoRevisao, AnuncioRevisao[]>;
type Aviso = { tipo: MensagemAcao["tipo"] | "error"; mensagem: string };

// Classes escritas por extenso.
const ALERTA: Record<Aviso["tipo"], string> = {
  success: "alert alert-success",
  info: "alert alert-info",
  warning: "alert alert-warning",
  error: "alert alert-error",
};

function semAnuncio(g: Grupos, id: number): Grupos {
  return {
    para_decidir: g.para_decidir.filter((a) => a.anuncio_id !== id),
    confirmados: g.confirmados.filter((a) => a.anuncio_id !== id),
    ignorados: g.ignorados.filter((a) => a.anuncio_id !== id),
  };
}

/** Põe o anúncio no grupo (tirando de onde estiver): na posição dada ou, sem ela, no começo. */
function comAnuncio(g: Grupos, grupo: GrupoRevisao, anuncio: AnuncioRevisao, indice = 0): Grupos {
  const limpo = semAnuncio(g, anuncio.anuncio_id);
  const lista = [...limpo[grupo]];
  lista.splice(Math.max(0, Math.min(indice, lista.length)), 0, anuncio);
  return { ...limpo, [grupo]: lista };
}

function destinoOtimista(acao: AcaoCasamento): GrupoRevisao {
  if (acao === "confirmar") return "confirmados";
  if (acao === "desfazer") return "para_decidir";
  return "ignorados";
}

function emCampo(alvo: EventTarget | null): boolean {
  if (!(alvo instanceof HTMLElement)) return false;
  return alvo.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(alvo.tagName);
}

export function RevisaoCasamento() {
  const { produtoId: idTexto } = useParams();
  const produtoId = Number(idTexto);
  const navigate = useNavigate();
  const { tratarErro } = useSessao();
  const [filtros] = useFiltrosUrl(PADROES);
  const query = montarQuery(filtros, true);
  const sufixo = query ? `?${query}` : "";
  const linkProduto = (id: number) => `/gestao/casamentos/${id}${sufixo}`;
  const voltar = `/gestao/casamentos${sufixo}`;

  const [dados, setDados] = useState<Revisao | null>(null);
  const [grupos, setGrupos] = useState<Grupos>({ para_decidir: [], confirmados: [], ignorados: [] });
  const [erro, setErro] = useState<{ status: number; mensagem: string } | null>(null);
  const [proximoFora, setProximoFora] = useState<number | null>(null);
  const [ocupados, setOcupados] = useState<Set<number>>(new Set());
  const [aviso, setAviso] = useState<Aviso | null>(null);
  const [selecionado, setSelecionado] = useState(0);
  const [trocando, setTrocando] = useState<AnuncioRevisao | null>(null);
  const [link, setLink] = useState("");
  // Cada carga da tela (outro produto ou a mesma de novo) ganha um número: resposta de ação pedida numa carga
  // anterior chega tarde e é descartada, para não cair nos grupos nem no aviso do produto que está na tela agora.
  const tela = useRef(0);

  const carregar = useCallback(
    async (sinal?: { cancelado: boolean }) => {
      setDados(null);
      setErro(null);
      setAviso(null);
      setProximoFora(null);
      setSelecionado(0);
      setOcupados(new Set());
      tela.current += 1;
      try {
        const r = await chamarApi<Revisao>(`/api/gestao/casamentos/${produtoId}${sufixo}`);
        if (sinal?.cancelado) return;
        setDados(r);
        setGrupos({ para_decidir: r.para_decidir, confirmados: r.confirmados, ignorados: r.ignorados });
      } catch (e) {
        if (sinal?.cancelado) return;
        const mensagem = tratarErro(e);
        if (mensagem === null) return;
        const status = e instanceof ErroApi ? e.status : 0;
        setErro({ status, mensagem });
        if (status !== 404) return;
        // O produto saiu do monitoramento: o próximo é o primeiro da lista filtrada que não seja ele.
        try {
          const lista = await chamarApi<ListaCasamentos>(`/api/gestao/casamentos${sufixo}`);
          if (sinal?.cancelado) return;
          setProximoFora(lista.itens.find((p) => p.id !== produtoId)?.id ?? null);
        } catch {
          // sem a lista, fica só o "Voltar à lista"
        }
      }
    },
    [produtoId, sufixo, tratarErro],
  );

  useEffect(() => {
    const sinal = { cancelado: false };
    void carregar(sinal);
    return () => {
      sinal.cancelado = true;
    };
  }, [carregar]);

  const decidir = useCallback(
    async (anuncio: AnuncioRevisao, de: GrupoRevisao, acao: AcaoCasamento, para?: number) => {
      const id = anuncio.anuncio_id;
      const minha = tela.current;
      const indice = grupos[de].findIndex((a) => a.anuncio_id === id);
      setAviso(null);
      setOcupados((o) => new Set(o).add(id));
      setGrupos((g) => comAnuncio(g, destinoOtimista(acao), anuncio));
      try {
        const corpo = acao === "trocar" ? { acao, para_produto_id: para } : { acao };
        const r = await chamarApi<DecisaoCasamento>(`/api/gestao/casamentos/${produtoId}/anuncios/${id}`, {
          metodo: "POST", corpo,
        });
        if (tela.current !== minha) return;
        setGrupos((g) => comAnuncio(g, r.grupo, r.anuncio));
        if (r.mensagem) setAviso({ tipo: "info", mensagem: r.mensagem });
      } catch (e) {
        if (tela.current !== minha) return;
        setGrupos((g) => comAnuncio(g, de, anuncio, indice));
        const mensagem = tratarErro(e);
        if (mensagem) setAviso({ tipo: "error", mensagem });
      } finally {
        if (tela.current === minha) setOcupados((o) => {
          const novo = new Set(o);
          novo.delete(id);
          return novo;
        });
      }
    },
    [grupos, produtoId, tratarErro],
  );

  const definirIdioma = async (anuncio: AnuncioRevisao, idioma: string) => {
    const id = anuncio.anuncio_id;
    const minha = tela.current;
    setAviso(null);
    setOcupados((o) => new Set(o).add(id));
    try {
      const r = await chamarApi<{ anuncio_id: number; idioma: string }>(
        `/api/gestao/casamentos/anuncios/${id}/idioma`, { metodo: "PATCH", corpo: { idioma } },
      );
      if (tela.current !== minha) return;
      setGrupos((g) => ({
        ...g,
        confirmados: g.confirmados.map((a) => (a.anuncio_id === id ? { ...a, idioma: r.idioma } : a)),
      }));
    } catch (e) {
      if (tela.current !== minha) return;
      const mensagem = tratarErro(e);
      if (mensagem) setAviso({ tipo: "error", mensagem });
    } finally {
      if (tela.current === minha) setOcupados((o) => {
        const novo = new Set(o);
        novo.delete(id);
        return novo;
      });
    }
  };

  const acaoDoTopo = async (caminho: "rebuscar" | "reavaliar" | "termos") => {
    (document.activeElement as HTMLElement | null)?.blur(); // fecha o menu ⋯
    setAviso(null);
    const minha = tela.current;
    try {
      const r = await chamarApi<MensagemAcao>(`/api/gestao/casamentos/${produtoId}/${caminho}`, { metodo: "POST" });
      if (tela.current !== minha) return;
      setAviso({ tipo: r.tipo, mensagem: r.mensagem });
    } catch (e) {
      if (tela.current !== minha) return;
      const mensagem = tratarErro(e);
      if (mensagem) setAviso({ tipo: "error", mensagem });
    }
  };

  const casarLink = async () => {
    const valor = link.trim();
    if (!valor) return;
    setAviso(null);
    const minha = tela.current;
    try {
      const novo = await chamarApi<AnuncioRevisao>(`/api/gestao/casamentos/${produtoId}/link`, {
        metodo: "POST", corpo: { link: valor },
      });
      if (tela.current !== minha) return;
      setGrupos((g) => comAnuncio(g, "confirmados", novo));
      setLink("");
      (document.activeElement as HTMLElement | null)?.blur();
      setAviso({ tipo: "success", mensagem: "Anúncio casado com este produto." });
    } catch (e) {
      if (tela.current !== minha) return;
      const mensagem = tratarErro(e);
      if (mensagem) setAviso({ tipo: "error", mensagem });
    }
  };

  const escolherOutro = (produto: ProdutoParecido) => {
    const anuncio = trocando;
    setTrocando(null);
    if (anuncio) void decidir(anuncio, "para_decidir", "trocar", produto.id);
  };

  // Atalhos: C, I, ↑/↓ e Enter, só com o foco fora de campo e sem janela aberta.
  const atalho = useRef<(ev: KeyboardEvent) => void>(() => {});
  atalho.current = (ev: KeyboardEvent) => {
    if (!dados || trocando || ev.ctrlKey || ev.metaKey || ev.altKey || emCampo(ev.target)) return;
    const pendentes = grupos.para_decidir;
    const atual = Math.min(selecionado, Math.max(0, pendentes.length - 1));
    const tecla = ev.key.toLowerCase();
    if (tecla === "arrowdown" || tecla === "arrowup") {
      if (pendentes.length === 0) return;
      ev.preventDefault();
      const passo = tecla === "arrowdown" ? 1 : -1;
      setSelecionado(Math.max(0, Math.min(pendentes.length - 1, atual + passo)));
    } else if ((tecla === "c" || tecla === "i") && pendentes[atual] && !ocupados.has(pendentes[atual].anuncio_id)) {
      ev.preventDefault();
      void decidir(pendentes[atual], "para_decidir", tecla === "c" ? "confirmar" : "ignorar");
    } else if (tecla === "enter" && dados.navegacao.proximo !== null) {
      const alvo = ev.target as HTMLElement | null;
      if (alvo && (alvo.tagName === "BUTTON" || alvo.tagName === "A")) return; // o Enter é do botão/link
      ev.preventDefault();
      navigate(linkProduto(dados.navegacao.proximo));
    }
  };
  useEffect(() => {
    const ouvir = (ev: KeyboardEvent) => atalho.current(ev);
    document.addEventListener("keydown", ouvir);
    return () => document.removeEventListener("keydown", ouvir);
  }, []);

  const alerta = aviso && (
    <div role="alert" className={ALERTA[aviso.tipo]}>
      <span>{aviso.mensagem}</span>
      <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAviso(null)}>Fechar</button>
    </div>
  );

  if (erro) {
    return (
      <section className="space-y-4">
        <Link className="btn btn-ghost btn-sm" to={voltar}>Voltar à lista</Link>
        <div role="alert" className={erro.status === 404 ? "alert alert-warning" : "alert alert-error"}>
          <span>{erro.mensagem}</span>
          {erro.status !== 404 && (
            <button type="button" className="btn btn-sm" onClick={() => void carregar()}>Tentar de novo</button>
          )}
        </div>
        {erro.status === 404 && proximoFora !== null && (
          <Link className="btn btn-primary btn-sm" to={linkProduto(proximoFora)}>Próximo produto →</Link>
        )}
      </section>
    );
  }
  if (dados === null) return <Carregando />;

  const { produto, navegacao } = dados;
  const atual = Math.min(selecionado, Math.max(0, grupos.para_decidir.length - 1));

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Link className="btn btn-ghost btn-sm" to={voltar}>Voltar à lista</Link>
        {navegacao.posicao > 0 ? (
          <span className="badge badge-ghost">{navegacao.posicao} de {navegacao.total}</span>
        ) : (
          <span className="badge badge-ghost">Fora da lista filtrada</span>
        )}
        <div className="join">
          {navegacao.anterior !== null ? (
            <Link className="btn btn-sm join-item" to={linkProduto(navegacao.anterior)}>← Anterior</Link>
          ) : (
            <button type="button" className="btn btn-sm join-item" disabled>← Anterior</button>
          )}
          {navegacao.proximo !== null ? (
            <>
              <Link className="btn btn-sm join-item" to={linkProduto(navegacao.proximo)} title="Próximo sem decidir">Pular</Link>
              <Link className="btn btn-primary btn-sm join-item" to={linkProduto(navegacao.proximo)}>Próximo →</Link>
            </>
          ) : (
            <>
              <button type="button" className="btn btn-sm join-item" disabled>Pular</button>
              <button type="button" className="btn btn-sm join-item" disabled>Próximo →</button>
            </>
          )}
        </div>
        <div className="dropdown dropdown-end ml-auto">
          <div tabIndex={0} role="button" className="btn btn-ghost btn-sm" aria-label="Mais ações">⋯</div>
          <div tabIndex={0} className="dropdown-content z-10 mt-2 w-72 rounded-box bg-base-100 p-2 shadow">
            <ul className="menu w-full p-0">
              <li><button type="button" onClick={() => void acaoDoTopo("rebuscar")}>Rebuscar agora</button></li>
              <li><button type="button" onClick={() => void acaoDoTopo("reavaliar")}>Reavaliar com a IA</button></li>
              <li><button type="button" onClick={() => void acaoDoTopo("termos")}>Gerar termos de busca</button></li>
            </ul>
            <form
              className="join mt-2 w-full"
              onSubmit={(ev) => {
                ev.preventDefault();
                void casarLink();
              }}
            >
              <input
                type="text" className="input input-sm join-item w-full" aria-label="Casar por link ou ASIN"
                placeholder="Casar por link ou ASIN" value={link} onChange={(ev) => setLink(ev.target.value)}
              />
              <button type="submit" className="btn btn-sm join-item">Casar</button>
            </form>
          </div>
        </div>
      </div>

      {alerta}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <aside className="space-y-3 self-start lg:sticky lg:top-4">
          <div className="card card-border card-sm bg-base-100">
            <div className="card-body">
              <div className="flex gap-3 lg:flex-col">
                <Foto src={produto.imagem} alt={produto.nome} tamanho="g" />
                <div className="min-w-0 space-y-1">
                  <h1 className="text-lg font-bold lg:text-xl">{produto.nome}</h1>
                  {produto.nome_en && produto.nome_en !== produto.nome && (
                    <p className="text-sm opacity-70">{produto.nome_en}</p>
                  )}
                  <div className="flex flex-wrap items-center gap-1 text-sm">
                    {produto.categoria && <span className="badge badge-outline badge-sm">{produto.categoria}</span>}
                    <span>a partir de <strong>{reais(produto.preco_liga)}</strong></span>
                    {produto.lojas !== null && <span className="opacity-70">· {produto.lojas} lojas</span>}
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {produto.pistas.map((p) => <span key={p} className="badge badge-ghost badge-sm">{p}</span>)}
                  </div>
                  <a className="link text-sm" href={produto.url} target="_blank" rel="noreferrer">Ver na LigaMagic ↗</a>
                </div>
              </div>
              {dados.parecidos.length > 0 && (
                <div className="space-y-1 pt-2">
                  <h2 className="text-sm font-semibold">Parecidos na Liga</h2>
                  <ul className="list" aria-label="Parecidos na Liga">
                    {dados.parecidos.map((p) => (
                      <li key={p.id} className="list-row items-center p-1">
                        <Foto src={p.imagem} alt={p.nome} tamanho="p" />
                        <Link className="link list-col-grow truncate text-sm" to={linkProduto(p.id)}>{p.nome}</Link>
                        <span className="text-xs opacity-70">{reais(p.preco_liga)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        </aside>

        <div className="min-w-0 space-y-6">
          <section className="space-y-2">
            <h2 className="text-lg font-semibold">Para decidir ({grupos.para_decidir.length})</h2>
            {grupos.para_decidir.length === 0 && <p className="text-sm opacity-70">Nada para decidir neste produto.</p>}
            <ul className="space-y-2" aria-label="Para decidir">
              {grupos.para_decidir.map((a, i) => (
                <li key={a.anuncio_id}>
                  <CartaoAnuncio
                    anuncio={a} grupo="para_decidir" ocupado={ocupados.has(a.anuncio_id)} selecionado={i === atual}
                    onDecidir={(acao) => (acao === "trocar" ? setTrocando(a) : void decidir(a, "para_decidir", acao))}
                  />
                </li>
              ))}
            </ul>
          </section>

          <section className="space-y-2">
            <h2 className="text-lg font-semibold">Confirmados ({grupos.confirmados.length})</h2>
            {grupos.confirmados.length === 0 && <p className="text-sm opacity-70">Nenhum anúncio confirmado.</p>}
            <ul className="space-y-2" aria-label="Confirmados">
              {grupos.confirmados.map((a) => (
                <li key={a.anuncio_id}>
                  <CartaoAnuncio
                    anuncio={a} grupo="confirmados" ocupado={ocupados.has(a.anuncio_id)}
                    onDecidir={(acao) => void decidir(a, "confirmados", acao)}
                    onDefinirIdioma={(idioma) => void definirIdioma(a, idioma)}
                  />
                </li>
              ))}
            </ul>
          </section>

          <div className="collapse collapse-arrow border border-base-300 bg-base-100">
            <input type="checkbox" aria-label="Mostrar ignorados" />
            <h2 className="collapse-title text-lg font-semibold">Ignorados ({grupos.ignorados.length})</h2>
            <div className="collapse-content">
              {grupos.ignorados.length === 0 && <p className="text-sm opacity-70">Nenhum anúncio ignorado.</p>}
              <ul className="space-y-2" aria-label="Ignorados">
                {grupos.ignorados.map((a) => (
                  <li key={a.anuncio_id}>
                    <CartaoAnuncio
                      anuncio={a} grupo="ignorados" ocupado={ocupados.has(a.anuncio_id)}
                      onDecidir={(acao) => void decidir(a, "ignorados", acao)}
                    />
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <p className="hidden text-xs opacity-70 lg:block">
            <kbd className="kbd kbd-sm">C</kbd> é o mesmo · <kbd className="kbd kbd-sm">I</kbd> não é ·{" "}
            <kbd className="kbd kbd-sm">↑</kbd> <kbd className="kbd kbd-sm">↓</kbd> anúncio ·{" "}
            <kbd className="kbd kbd-sm">Enter</kbd> próximo produto
          </p>
        </div>
      </div>

      {trocando && (
        <ModalOutroProduto
          anuncio={trocando} produtoId={produto.id} aoEscolher={escolherOutro} aoFechar={() => setTrocando(null)}
        />
      )}
    </section>
  );
}
