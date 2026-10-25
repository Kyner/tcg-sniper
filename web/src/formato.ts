// Formatos da área de negócio: reais e % em pt-BR, duração curta, data e hora no fuso do navegador.
import type { Motivo } from "./tipos";

const MOEDA = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const PCT = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const DATA_HORA = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const DATA = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit" });
const DATA_ANO = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" });

export function reais(valor: string | null): string {
  // O Intl usa espaço não separável depois de "R$"; trocamos por espaço comum.
  return valor === null ? "—" : MOEDA.format(Number(valor)).replace(/ /g, " ");
}

export function pct(valor: string | null): string {
  return valor === null ? "—" : `${PCT.format(Number(valor))}%`;
}

export function duracao(minutos: number | null): string {
  if (minutos === null) return "—";
  if (minutos < 60) return `${minutos} min`;
  const dias = Math.floor(minutos / 1440);
  const horas = Math.floor((minutos % 1440) / 60);
  const resto = minutos % 60;
  if (dias > 0) return horas > 0 ? `${dias} d ${horas} h` : `${dias} d`;
  return resto > 0 ? `${horas} h ${resto} min` : `${horas} h`;
}

export const dataHora = (iso: string) => DATA_HORA.format(new Date(iso));
export const dataCurta = (iso: string) => DATA.format(new Date(iso));
export const dataComAno = (iso: string) => DATA_ANO.format(new Date(iso));

const HORA = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });
/** HH:MM no fuso do navegador. */
export const horaMinuto = (iso: string) => HORA.format(new Date(iso));

/** Iguais aos dos avisos do WhatsApp (oportunidades/mensagens.ROTULOS_MOTIVO). */
export const ROTULOS_MOTIVO: Record<Motivo, string> = {
  preco_subiu: "preço subiu",
  oferta_sumiu: "oferta sumiu",
  liga_caiu: "Liga baixou",
  vendedor: "vendedor mudou",
  liga_desatualizada: "preço da Liga desatualizado",
  sem_leitura: "anúncio sem leitura",
  casamento_desfeito: "casamento desfeito",
};
