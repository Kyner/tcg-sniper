// Gestão: revisão dos anúncios da Amazon de um produto da Liga. A query da lista (filtros, ordem e página) vem
// na URL e segue igual para a API, para "Voltar à lista" e para Anterior/Próximo. As partes da tela ficam em
// `./revisao/`; aqui ficam o estado, as chamadas e os atalhos.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { chamarApi, ErroApi } from "../../api";
import { Carregando } from "../../componentes/Carregando";
import { ModalOutroProduto } from "../../componentes/ModalOutroProduto";
import { useFiltrosUrl } from "../../filtrosUrl";
import { useSessao } from "../../sessao";
import type {
  AcaoCasamento, AnuncioRevisao, DecisaoCasamento, GrupoRevisao, ListaCasamentos, MensagemAcao, ProdutoParecido,
  RevisaoCasamento as Revisao,
} from "../../tipos";
import { montarQuery, PADROES } from "./Casamentos";
import { BarraRevisao, type AcaoTopo } from "./revisao/BarraRevisao";
import { comAnuncio, destinoOtimista, GRUPOS_VAZIOS, idDoCartao, type Aviso, type Grupos } from "./revisao/grupos";
import { GruposAnuncios } from "./revisao/GruposAnuncios";
import { ParecidosNaLiga, ProdutoDaLiga } from "./revisao/ProdutoDaLiga";

// Classes escritas por extenso.
const ALERTA: Record<Aviso["tipo"], string> = {
  success: "alert alert-success",
  info: "alert alert-info",
  warning: "alert alert-warning",
  error: "alert alert-error",
};

function emCampo(alvo: EventTarget | null): boolean {
  if (!(alvo instanceof HTMLElement)) return false;
  return alvo.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(alvo.tagName);
}

/** O Enter é do elemento com foco (botão, link, menu ⋯), não do atalho "próximo produto". */
function enterDoElemento(alvo: EventTarget | null): boolean {
  return alvo instanceof Element && alvo.closest("button, a, [role=button], .dropdown") !== null;
}

export function RevisaoCasamento() {
  const { produtoId: idTexto } = useParams();
  const produtoId = Number(idTexto);
  const navigate = useNavigate();
  const { tratarErro } = useSessao();
  const [filtros] = useFiltrosUrl(PADROES);
  const query = montarQuery(filtros, true);
  const sufixo = query ? `?${query}` : "";
  const linkProduto = useCallback((id: number) => `/gestao/casamentos/${id}${sufixo}`, [sufixo]);
  const voltar = `/gestao/casamentos${sufixo}`;

  const [dados, setDados] = useState<Revisao | null>(null);
  const [grupos, setGrupos] = useState<Grupos>(GRUPOS_VAZIOS);
  const [erro, setErro] = useState<{ status: number; mensagem: string } | null>(null);
  const [proximoFora, setProximoFora] = useState<number | null>(null);
  const [ocupados, setOcupados] = useState<Set<number>>(new Set());
  const [aviso, setAviso] = useState<Aviso | null>(null);
  // O destaque segue o anúncio (não a posição): um "desfazer" que entra acima não o troca. Se o destacado sai de
  // "Para decidir", vale a última posição (o seguinte ocupa o lugar dele).
  const [destacadoId, setDestacadoId] = useState<number | null>(null);
  const posicao = useRef(0);
  const rolar = useRef(false);
  const [trocando, setTrocando] = useState<AnuncioRevisao | null>(null);
  // Cada carga da tela (outro produto ou a mesma de novo) ganha um número: resposta de ação pedida numa carga
  // anterior chega tarde e é descartada, para não cair nos grupos nem no aviso do produto que está na tela agora.
  const tela = useRef(0);

  const carregar = useCallback(
    async (sinal?: { cancelado: boolean }) => {
      setDados(null);
      setErro(null);
      setAviso(null);
      setProximoFora(null);
      setDestacadoId(null);
      posicao.current = 0;
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

  useEffect(() => {
    if (!rolar.current || destacadoId === null) return;
    rolar.current = false;
    document.getElementById(idDoCartao(destacadoId))?.scrollIntoView?.({ block: "nearest" });
  }, [destacadoId]);

  const tirarOcupado = (id: number) => setOcupados((o) => {
    const novo = new Set(o);
    novo.delete(id);
    return novo;
  });

  const decidir = useCallback(
    async (anuncio: AnuncioRevisao, de: GrupoRevisao, acao: AcaoCasamento, para?: number) => {
      const id = anuncio.anuncio_id;
      const minha = tela.current;
      const indice = grupos[de].findIndex((a) => a.anuncio_id === id);
      setAviso(null);
      setOcupados((o) => new Set(o).add(id));
      setDestacadoId((d) => (d === id ? null : d));
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
        if (tela.current === minha) tirarOcupado(id);
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
      if (tela.current === minha) tirarOcupado(id);
    }
  };

  const acaoDoTopo = async (caminho: AcaoTopo) => {
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

  const casarLink = async (valor: string): Promise<boolean> => {
    setAviso(null);
    const minha = tela.current;
    try {
      const novo = await chamarApi<AnuncioRevisao>(`/api/gestao/casamentos/${produtoId}/link`, {
        metodo: "POST", corpo: { link: valor },
      });
      if (tela.current !== minha) return false;
      setGrupos((g) => comAnuncio(g, "confirmados", novo));
      (document.activeElement as HTMLElement | null)?.blur();
      setAviso({ tipo: "success", mensagem: "Anúncio casado com este produto." });
      return true;
    } catch (e) {
      if (tela.current !== minha) return false;
      const mensagem = tratarErro(e);
      if (mensagem) setAviso({ tipo: "error", mensagem });
      return false;
    }
  };

  const escolherOutro = (produto: ProdutoParecido) => {
    const anuncio = trocando;
    setTrocando(null);
    if (anuncio) void decidir(anuncio, "para_decidir", "trocar", produto.id);
  };

  const pendentes = grupos.para_decidir;
  const achado = destacadoId === null ? -1 : pendentes.findIndex((a) => a.anuncio_id === destacadoId);
  const atual = achado >= 0 ? achado : Math.min(posicao.current, Math.max(0, pendentes.length - 1));
  posicao.current = atual;

  // Atalhos: C, I, ↑/↓ e Enter, só com o foco fora de campo e sem janela aberta.
  const atalho = useRef<(ev: KeyboardEvent) => void>(() => {});
  atalho.current = (ev: KeyboardEvent) => {
    if (!dados || trocando || ev.ctrlKey || ev.metaKey || ev.altKey || emCampo(ev.target)) return;
    const tecla = ev.key.toLowerCase();
    if (tecla === "arrowdown" || tecla === "arrowup") {
      if (pendentes.length === 0) return;
      ev.preventDefault();
      const passo = tecla === "arrowdown" ? 1 : -1;
      const novo = Math.max(0, Math.min(pendentes.length - 1, atual + passo));
      posicao.current = novo;
      rolar.current = true;
      setDestacadoId(pendentes[novo].anuncio_id);
    } else if ((tecla === "c" || tecla === "i") && pendentes[atual] && !ocupados.has(pendentes[atual].anuncio_id)) {
      ev.preventDefault();
      void decidir(pendentes[atual], "para_decidir", tecla === "c" ? "confirmar" : "ignorar");
    } else if (tecla === "enter" && dados.navegacao.proximo !== null) {
      if (enterDoElemento(ev.target)) return;
      ev.preventDefault();
      navigate(linkProduto(dados.navegacao.proximo));
    }
  };
  useEffect(() => {
    const ouvir = (ev: KeyboardEvent) => atalho.current(ev);
    document.addEventListener("keydown", ouvir);
    return () => document.removeEventListener("keydown", ouvir);
  }, []);

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

  return (
    <section className="space-y-4">
      <BarraRevisao
        navegacao={dados.navegacao} voltar={voltar} linkProduto={linkProduto}
        aoAcao={(acao) => void acaoDoTopo(acao)} aoCasarLink={casarLink}
      />

      {aviso && (
        <div role="alert" className={ALERTA[aviso.tipo]}>
          <span>{aviso.mensagem}</span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAviso(null)}>Fechar</button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        {/* No celular o aside some (contents) e o produto, os anúncios e os parecidos se ordenam pelo order-*. */}
        <aside className="contents lg:sticky lg:top-4 lg:block lg:space-y-3 lg:self-start">
          <ProdutoDaLiga produto={dados.produto} />
          <ParecidosNaLiga parecidos={dados.parecidos} linkProduto={linkProduto} />
        </aside>
        <GruposAnuncios
          grupos={grupos} ocupados={ocupados} destacado={atual}
          aoDecidir={(a, de, acao) => void decidir(a, de, acao)} aoTrocar={setTrocando}
          aoDefinirIdioma={(a, idioma) => void definirIdioma(a, idioma)}
        />
      </div>

      {trocando && (
        <ModalOutroProduto
          anuncio={trocando} produtoId={dados.produto.id} aoEscolher={escolherOutro} aoFechar={() => setTrocando(null)}
        />
      )}
    </section>
  );
}
