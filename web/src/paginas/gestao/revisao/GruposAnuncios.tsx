// Os três grupos de anúncios da revisão (para decidir, confirmados, ignorados) e a legenda dos atalhos.
import { CartaoAnuncio } from "../../../componentes/CartaoAnuncio";
import type { AcaoCasamento, AnuncioRevisao, GrupoRevisao } from "../../../tipos";
import { idDoCartao, type Grupos } from "./grupos";

export function GruposAnuncios({
  grupos, ocupados, destacado, aoDecidir, aoTrocar, aoDefinirIdioma,
}: {
  grupos: Grupos;
  ocupados: Set<number>;
  /** Posição do cartão destacado em "Para decidir". */
  destacado: number;
  aoDecidir: (anuncio: AnuncioRevisao, de: GrupoRevisao, acao: AcaoCasamento) => void;
  aoTrocar: (anuncio: AnuncioRevisao) => void;
  aoDefinirIdioma: (anuncio: AnuncioRevisao, idioma: string) => void;
}) {
  return (
    <div className="order-2 min-w-0 space-y-6 lg:order-none">
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Para decidir ({grupos.para_decidir.length})</h2>
        {grupos.para_decidir.length === 0 && <p className="text-sm opacity-70">Nada para decidir neste produto.</p>}
        <ul className="space-y-2" aria-label="Para decidir">
          {grupos.para_decidir.map((a, i) => (
            <li key={a.anuncio_id} id={idDoCartao(a.anuncio_id)}>
              <CartaoAnuncio
                anuncio={a} grupo="para_decidir" ocupado={ocupados.has(a.anuncio_id)} selecionado={i === destacado}
                onDecidir={(acao) => (acao === "trocar" ? aoTrocar(a) : aoDecidir(a, "para_decidir", acao))}
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
                onDecidir={(acao) => aoDecidir(a, "confirmados", acao)}
                onDefinirIdioma={(idioma) => aoDefinirIdioma(a, idioma)}
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
                  onDecidir={(acao) => aoDecidir(a, "ignorados", acao)}
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
  );
}
