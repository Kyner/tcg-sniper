// Os três grupos de anúncios da revisão e as trocas otimistas entre eles.
import type { AcaoCasamento, AnuncioRevisao, GrupoRevisao, MensagemAcao } from "../../../tipos";

export type Grupos = Record<GrupoRevisao, AnuncioRevisao[]>;
export type Aviso = { tipo: MensagemAcao["tipo"] | "error"; mensagem: string };

export const GRUPOS_VAZIOS: Grupos = { para_decidir: [], confirmados: [], ignorados: [] };

export function semAnuncio(g: Grupos, id: number): Grupos {
  return {
    para_decidir: g.para_decidir.filter((a) => a.anuncio_id !== id),
    confirmados: g.confirmados.filter((a) => a.anuncio_id !== id),
    ignorados: g.ignorados.filter((a) => a.anuncio_id !== id),
  };
}

/** Põe o anúncio no grupo (tirando de onde estiver): na posição dada ou, sem ela, no começo. */
export function comAnuncio(g: Grupos, grupo: GrupoRevisao, anuncio: AnuncioRevisao, indice = 0): Grupos {
  const limpo = semAnuncio(g, anuncio.anuncio_id);
  const lista = [...limpo[grupo]];
  lista.splice(Math.max(0, Math.min(indice, lista.length)), 0, anuncio);
  return { ...limpo, [grupo]: lista };
}

export function destinoOtimista(acao: AcaoCasamento): GrupoRevisao {
  if (acao === "confirmar") return "confirmados";
  if (acao === "desfazer") return "para_decidir";
  return "ignorados";
}

/** O id do elemento da lista de um anúncio (para rolar até ele). */
export const idDoCartao = (anuncioId: number) => `anuncio-${anuncioId}`;
