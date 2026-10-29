/** Página do produto na Amazon Brasil a partir do ASIN. */
export function enderecoAmazon(asin: string): string {
  return `https://www.amazon.com.br/dp/${encodeURIComponent(asin)}`;
}
