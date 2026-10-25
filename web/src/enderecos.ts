// Endereço do admin antigo (porta 8000 no mesmo PC), para as telas que ainda não mudaram para cá.
export function enderecoAdminAntigo(caminho = ""): string {
  return `${window.location.protocol}//${window.location.hostname}:8000/${caminho}`;
}

/** Página do produto na Amazon Brasil a partir do ASIN. */
export function enderecoAmazon(asin: string): string {
  return `https://www.amazon.com.br/dp/${encodeURIComponent(asin)}`;
}
